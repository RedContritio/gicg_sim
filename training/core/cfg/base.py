"""ParadigmConfigBase — base dataclass for paradigm-agnostic metadata.

Spec ref: config-schema/spec.md § 7 N2 (cfg-schema-unification delta).

Each paradigm's root config (``AZParadigmConfig`` / ``BCParadigmConfig`` / ...)
SHALL compose this base via dataclass inheritance, providing:

- ``version``: cfg schema version (bump on any field change to detect
  ckpt-cfg mismatch at load time, per spec N3)
- ``paradigm``: identifier string ('az' | 'bc' | 'cfr' | 'dmc' | 'ppo')
  matching the dispatch key (per spec N3.3)

The base does not declare a shape field. Each subclass provides its own
``agent: ObsShape`` field, preserving the ``pcfg.agent.X`` caller interface
while sharing the shape type across paradigms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ParadigmConfigBase:
    """Base for paradigm-specific configs.

    Subclass usage:

        @dataclass(frozen=True)
        class AZParadigmConfig(ParadigmConfigBase):
            paradigm: str = 'az'
            agent: ObsShape = field(default_factory=make_az_default_shape)
            mcts: MCTSCfg = field(default_factory=MCTSCfg)
            train: TrainStepCfg = field(default_factory=TrainStepCfg)
            # ... other paradigm-specific fields ...

            @classmethod
            def from_dict(cls, d):
                return cls.from_dict_strict(
                    d,
                    paradigm_name='az',
                    supported_versions=_AZ_SUPPORTED_VERSIONS,
                    sub_section_factories={
                        'agent': lambda dd: build_shape_from_toml(dd, make_az_default_shape),
                        'mcts': lambda dd: MCTSCfg(**dd),
                        'train': lambda dd: TrainStepCfg(**dd),
                    },
                )
    """

    version: str = '1.0.0'
    paradigm: str = ''

    @classmethod
    def from_dict_strict(
        cls,
        d: dict,
        *,
        paradigm_name: str,
        supported_versions: frozenset[str],
        sub_section_factories: dict[str, Callable[[dict], Any]] | None = None,
    ) -> 'ParadigmConfigBase':
        """Validate and convert a paradigm config dict to its dataclass.

        - Unknown top-level key in ``d`` SHALL raise (CS4 strict unknown-key)
        - ``d['version']`` (if present) SHALL be in ``supported_versions``
          (default '1.0.0' if absent)
        - ``d['paradigm']`` (if present) SHALL equal ``paradigm_name``
        - Each key in ``sub_section_factories`` is treated as a nested
          dict to be passed through the factory function before being
          forwarded as a kwarg to ``cls(**kwargs)``. Non-dict values
          (e.g. dataclass instance pre-built by caller) pass through
          unchanged so the helper is reusable in non-toml contexts.

        Subclass-specific post-processing (deprecated-key translation,
        enum-value validation, list→tuple coercion) SHALL happen in the
        subclass's ``from_dict`` wrapper around this helper.
        """
        factories = sub_section_factories or {}

        allowed = set(cls.__dataclass_fields__.keys())
        unknown = set(d.keys()) - allowed
        if unknown:
            raise ValueError(
                f'{cls.__name__}.from_dict: unknown paradigm key(s) {sorted(unknown)} (allowed: {sorted(allowed)})'
            )

        version = d.get('version', '1.0.0')
        if version not in supported_versions:
            raise ValueError(
                f'{cls.__name__}: unsupported version {version!r} (supported: {sorted(supported_versions)})'
            )

        paradigm_val = d.get('paradigm', paradigm_name)
        if paradigm_val != paradigm_name:
            raise ValueError(f'{cls.__name__}: paradigm mismatch: expected {paradigm_name}, got {paradigm_val!r}')

        kwargs = {k: v for k, v in d.items() if k not in factories}
        for section, factory in factories.items():
            if section not in d:
                continue
            section_val = d[section]
            if isinstance(section_val, dict):
                kwargs[section] = factory(section_val)
            else:
                kwargs[section] = section_val

        return cls(**kwargs)
