"""Tests for cfg-schema-unification N3 — version + paradigm field validation.

Spec ref: config-schema/spec.md § 7 N3.2 (version enum) + N3.3 (paradigm mismatch).
"""

from __future__ import annotations

import pytest

from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.bc.config import BCParadigmConfig
from training.paradigms.cfr.config import CFRParadigmConfig
from training.paradigms.dmc.config import DMCParadigmConfig


# ---------- N3.1 / N3.4: default behavior (empty dict / no version key) ---------- #


@pytest.mark.parametrize(
    'cls,expected_paradigm',
    [
        (AZParadigmConfig, 'az'),
        (BCParadigmConfig, 'bc'),
        (CFRParadigmConfig, 'cfr'),
        (DMCParadigmConfig, 'dmc'),
    ],
)
def test_from_dict_empty_succeeds_with_defaults(cls, expected_paradigm):
    """from_dict({}) succeeds with default version + paradigm (N3.4)."""
    cfg = cls.from_dict({})
    assert cfg.version == '1.0.0'
    assert cfg.paradigm == expected_paradigm


@pytest.mark.parametrize(
    'cls',
    [AZParadigmConfig, BCParadigmConfig, CFRParadigmConfig, DMCParadigmConfig],
)
def test_from_dict_explicit_version_1_0_0_succeeds(cls):
    """from_dict({'version': '1.0.0'}) explicit current version OK (N3.2)."""
    cfg = cls.from_dict({'version': '1.0.0'})
    assert cfg.version == '1.0.0'


# ---------- N3.2: unsupported version raises ---------- #


@pytest.mark.parametrize(
    'cls,paradigm_name',
    [
        (AZParadigmConfig, 'az'),
        (BCParadigmConfig, 'bc'),
        (CFRParadigmConfig, 'cfr'),
        (DMCParadigmConfig, 'dmc'),
    ],
)
def test_from_dict_unsupported_version_raises(cls, paradigm_name):
    """from_dict({'version': '1.5.0'}) → raise 'unsupported version' (N3.2)."""
    with pytest.raises(ValueError, match='unsupported version'):
        cls.from_dict({'version': '1.5.0'})


@pytest.mark.parametrize(
    'cls',
    [AZParadigmConfig, BCParadigmConfig, CFRParadigmConfig, DMCParadigmConfig],
)
def test_from_dict_typo_version_raises(cls):
    """Typo (e.g. '1.0' missing patch) raises (defensive enum)."""
    with pytest.raises(ValueError, match='unsupported version'):
        cls.from_dict({'version': '1.0'})


# ---------- N3.3: paradigm mismatch raises ---------- #


@pytest.mark.parametrize(
    'cls,wrong_paradigm',
    [
        (AZParadigmConfig, 'bc'),
        (AZParadigmConfig, 'dmc'),
        (BCParadigmConfig, 'az'),
        (BCParadigmConfig, 'cfr'),
        (CFRParadigmConfig, 'dmc'),
        (CFRParadigmConfig, 'az'),
        (DMCParadigmConfig, 'cfr'),
        (DMCParadigmConfig, 'bc'),
    ],
)
def test_from_dict_paradigm_mismatch_raises(cls, wrong_paradigm):
    """from_dict({'paradigm': '<other>'}) → raise 'paradigm mismatch' (N3.3 / CC-205)."""
    with pytest.raises(ValueError, match='paradigm mismatch'):
        cls.from_dict({'paradigm': wrong_paradigm})


@pytest.mark.parametrize(
    'cls,own_paradigm',
    [
        (AZParadigmConfig, 'az'),
        (BCParadigmConfig, 'bc'),
        (CFRParadigmConfig, 'cfr'),
        (DMCParadigmConfig, 'dmc'),
    ],
)
def test_from_dict_paradigm_matching_succeeds(cls, own_paradigm):
    """from_dict({'paradigm': own_name}) succeeds (matches dispatch key)."""
    cfg = cls.from_dict({'paradigm': own_paradigm})
    assert cfg.paradigm == own_paradigm


# ---------- Combined: version + paradigm both specified ---------- #


def test_az_from_dict_full_metadata():
    """AZ from_dict with both version + paradigm explicit OK."""
    cfg = AZParadigmConfig.from_dict({'version': '1.0.0', 'paradigm': 'az'})
    assert cfg.version == '1.0.0'
    assert cfg.paradigm == 'az'


def test_dmc_from_dict_with_agent_subdict():
    """DMC from_dict allows version + paradigm + nested agent fields."""
    cfg = DMCParadigmConfig.from_dict(
        {
            'version': '1.0.0',
            'paradigm': 'dmc',
            'epsilon': 0.1,
            'agent': {'d_model': 16},
        }
    )
    assert cfg.version == '1.0.0'
    assert cfg.paradigm == 'dmc'
    assert cfg.epsilon == 0.1
    assert cfg.agent.d_model == 16
    # Other agent fields fall back to factory defaults
    assert cfg.agent.n_cross_layers == 1
    assert cfg.agent.n_counter_slots == 2 * 6 * 128 + 2 * 140 + 16
