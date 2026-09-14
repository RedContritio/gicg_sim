"""Contract test:tools.dataset.gen_bc 单一 schema 输出(AZ-shape only)。

Post-dedupe contract(FU-W2A-followup B2):
> ``tools.dataset.gen_bc`` 产 dataset SHALL 只有一个 schema —— AZ-shape
> (game_static_obs + game_id + dyn_obs + action_refs + action_payments +
> legal_mask + tied_mask + chosen_action + terminal_z),由 active
> ``training.paradigms.bc.dataset.BCDataset`` 直接加载。
> dispatcher SHALL NOT 再有 paradigm / variant 分支(B1 已 retire PPO 变体)。

This file guards three post-dedupe invariants:

1. **Module surface** — ``tools.dataset.gen_bc`` SHALL NOT 再 import
   ``tools.dataset.gen_bc_ppo``。PPO-shape source file SHALL be removed。
2. **CLI surface** — ``python -m tools.dataset.gen_bc --help`` SHALL NOT
   提及 ``paradigm`` / ``variant`` / ``ppo`` / ``F1-D2``(无 dispatch 概念)。
3. **Output schema** — ``gen_bc.collect()`` 跑 tiny smoke 产 dict 含
   AZ-shape 全 9 字段;output ``dataset.npz`` 可被 BCDataset 直接 load。

第三项是 end-to-end contract:engine boot + greedy teacher rollout 需
~3-5 s,所以本测试只跑 2 局 / target_decisions=20 的最小 smoke。

Source of truth for the canonical AZ schema is
``training/paradigms/bc/dataset.py`` —— 任何字段加减都先改 BCDataset
再改这里。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable


# Canonical AZ-shape NPZ fields — must match BCDataset.__init__ reads.
_AZ_SHAPE_NPZ_KEYS = frozenset(
    {
        'game_static_obs',
        'game_id',
        'dyn_obs',
        'action_refs',
        'action_payments',
        'legal_mask',
        'tied_mask',
        'chosen_action',
        'terminal_z',
    }
)


def test_no_ppo_variant_module_imported() -> None:
    """tools.dataset.gen_bc SHALL NOT import gen_bc_ppo.

    After B2 dedupe,PPO-shape path is gone;dispatcher 不再有 variant
    branch,所以 source SHALL NOT 出现 ``gen_bc_ppo`` token in import
    or function-body code(docstring / comment 允许 historical reference)。
    """
    import ast

    src_path = REPO_ROOT / 'tools' / 'dataset' / 'gen_bc.py'
    src = src_path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert 'gen_bc_ppo' not in mod, (
                f'tools/dataset/gen_bc.py L{node.lineno} still imports gen_bc_ppo: '
                f'{ast.dump(node)} — B2 dedupe leftover'
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'gen_bc_ppo' not in alias.name, (
                    f'tools/dataset/gen_bc.py L{node.lineno} still imports gen_bc_ppo: {alias.name}'
                )


def test_no_ppo_variant_source_file() -> None:
    """tools/dataset/gen_bc_ppo.py SHALL not exist post-dedupe."""
    p = REPO_ROOT / 'tools' / 'dataset' / 'gen_bc_ppo.py'
    assert not p.exists(), (
        f'{p} still present — B2 dedupe leftover (BC PPO variant retired in commit adc6db2/2d0584b/1cb1bec)'
    )


def test_cli_help_has_no_variant_flag() -> None:
    """``python -m tools.dataset.gen_bc --help`` SHALL NOT mention
    variant / paradigm / ppo / F1-D2(dispatcher 概念已消失)。"""
    result = subprocess.run(
        [PYTHON, '-m', 'tools.dataset.gen_bc', '--help'],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, f'--help exit {result.returncode}\nstderr:\n{result.stderr}'
    text = (result.stdout + result.stderr).lower()
    # Banned tokens that signal residual variant dispatch in --help text。
    # ``paradigm`` lowercased,covers both "paradigm" docstring + cfg field hint。
    for banned in ('--variant', '--paradigm', 'gen_bc_ppo', 'ppo-shape', 'ppo shape'):
        assert banned not in text, (
            f'gen_bc --help still mentions {banned!r}:\n{result.stdout}\n--- stderr ---\n{result.stderr}'
        )


def test_collect_produces_az_shape_only() -> None:
    """Real smoke: invoke ``tools.dataset.gen_bc collect`` 跑 tiny config,
    verify output NPZ keys == AZ-shape canonical set,且 BCDataset 可 load。

    使用现有 ``configs/smoke/smoke_bc_data_gen_container.toml`` 作模板;
    缩 target_decisions / max_games 到极小;output 写 tmpdir,跑完即清。
    """
    from tools.dataset.gen_bc import collect

    src_cfg_path = (
        REPO_ROOT / 'configs' / '_archived' / 'pre_redesign_2026_05_17' / 'smoke' / 'smoke_bc_data_gen_container.toml'
    )
    assert src_cfg_path.exists(), f'missing smoke cfg template: {src_cfg_path}'

    import tomllib

    with src_cfg_path.open('rb') as f:
        cfg = tomllib.load(f)

    # Tiny smoke override — keep wall ≤ ~10 s
    cfg['target_decisions'] = 20
    cfg['max_games'] = 5
    # smoke cfg omits 'pool'(filler default = test_basic in container);
    # outside container we must set explicitly so engine resolves 测试角色D。
    cfg.setdefault('pool', 'test_basic')

    data = collect(cfg)

    # Field set check —— canonical AZ-shape,no extras / no PPO-shape
    # PPO-shape would have 'obs' (flat) + 'action' (int64) + 'episode_id';
    # AZ-shape has 'dyn_obs' + 'chosen_action' (int32) + 'game_id' +
    # 'game_static_obs' + 'action_refs' + 'action_payments' (+ shared
    # 'legal_mask' / 'tied_mask' / 'terminal_z')。
    npz_keys = {k for k in data.keys() if k != 'meta'}
    assert npz_keys == _AZ_SHAPE_NPZ_KEYS, (
        f'gen_bc collect produced wrong key set\n  got: {sorted(npz_keys)}\n  '
        f'expected: {sorted(_AZ_SHAPE_NPZ_KEYS)}\n  '
        f'extra: {sorted(npz_keys - _AZ_SHAPE_NPZ_KEYS)}\n  '
        f'missing: {sorted(_AZ_SHAPE_NPZ_KEYS - npz_keys)}'
    )

    # PPO-shape-only fields SHALL not slip in via partial dedupe
    for banned in ('obs', 'action', 'episode_id'):
        assert banned not in data, f'PPO-shape field {banned!r} leaked into AZ-shape dataset'

    # Shape sanity:n_decisions consistent across per-step arrays
    n = int(data['chosen_action'].shape[0])
    assert n > 0, 'smoke produced 0 decisions — env / teacher misconfigured'
    for key in ('game_id', 'dyn_obs', 'action_refs', 'action_payments', 'legal_mask', 'tied_mask', 'terminal_z'):
        assert data[key].shape[0] == n, f'AZ-shape field {key} length {data[key].shape[0]} != chosen_action length {n}'

    # Persist + roundtrip through BCDataset to assert load contract
    with tempfile.TemporaryDirectory() as tmpdir:
        npz_path = Path(tmpdir) / 'dataset.npz'
        np_kwargs = {k: v for k, v in data.items() if k != 'meta'}
        from training.core.artifact_io import save_dataset

        save_dataset(npz_path, **np_kwargs)
        # Persist meta too for completeness;BCDataset doesn't need it
        with (Path(tmpdir) / 'meta.json').open('w', encoding='utf-8') as f:
            json.dump(data['meta'], f, ensure_ascii=False, indent=2)

        # Post core-network-generic-promotion: BCDataset moved from
        # paradigms.bc.legacy.bc_dataset to paradigms.bc.dataset.
        from training.paradigms.bc.dataset import BCDataset

        # AgentConfig defaults pulled from BCParadigmConfig.AgentShapeCfg
        # to match production load shape;cheap NPZ → in-memory parse。
        ds = BCDataset(
            npz_path,
            n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
            n_hooks=900,
            max_ops_per_hook=64,
        )
        assert len(ds) == n, f'BCDataset reports {len(ds)} decisions, gen_bc produced {n}'
        # build_batch on first index should not raise
        batch = ds.build_batch(np.asarray([0], dtype=np.int64))
        assert 'chosen_action' in batch and 'legal_mask' in batch, 'BCDataset.build_batch missing core keys'


@pytest.mark.parametrize('legacy_field', ['teacher_paradigm', 'paradigm'])
def test_legacy_paradigm_field_in_cfg_is_ignored_or_unused(legacy_field: str) -> None:
    """Legacy top-level ``teacher_paradigm`` / ``paradigm`` cfg fields are
    no longer consulted by gen_bc(dispatcher gone). Setting them SHALL
    NOT raise(ignored)nor change behaviour。"""
    import ast

    src = (REPO_ROOT / 'tools' / 'dataset' / 'gen_bc.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    # No function in the module body should call cfg.get(<legacy_field>)
    # or subscript cfg[<legacy_field>] — that would mean the dispatcher
    # still reads it。Quick AST scan:walk for ast.Subscript on cfg with
    # the constant name,and ast.Call cfg.get(<legacy_field>)。
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == legacy_field
            ):
                pytest.fail(
                    f'tools/dataset/gen_bc.py L{node.lineno} still reads legacy cfg field '
                    f'{legacy_field!r} via .get() — variant dispatch leftover'
                )
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and node.slice.value == legacy_field:
                pytest.fail(
                    f'tools/dataset/gen_bc.py L{node.lineno} still reads legacy cfg field '
                    f'{legacy_field!r} via subscript — variant dispatch leftover'
                )


def test_unknown_cfg_key_raises(tmp_path) -> None:
    """Per CLAUDE.md "意外输入必须抛异常":a stale or typo cfg key(e.g.
    ``teacher_paradigm`` from pre-dedupe era,or ``paradigm`` from variant
    dispatcher era)SHALL raise loudly at main() entry,not silently produce
    AZ-shape data while user thinks PPO-shape is being honoured。

    Test method:copy the smoke cfg verbatim,inject one bogus top-level
    key,assert main() raises ValueError mentioning ``unknown cfg key``。
    """
    from tools.dataset.gen_bc import main

    src_cfg_path = (
        REPO_ROOT / 'configs' / '_archived' / 'pre_redesign_2026_05_17' / 'smoke' / 'smoke_bc_data_gen_container.toml'
    )
    cfg_text = src_cfg_path.read_text(encoding='utf-8')
    # Inject a top-level legacy/typo key BEFORE any TOML section header so
    # it lands at the top level(not inside ``[meta]``)。
    bogus_cfg_text = 'teacher_paradigm = "ppo"\n' + cfg_text

    bad_cfg_path = tmp_path / 'bad.toml'
    bad_cfg_path.write_text(bogus_cfg_text, encoding='utf-8')

    with pytest.raises(ValueError, match='unknown cfg key'):
        main([str(bad_cfg_path)])
