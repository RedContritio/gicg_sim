"""A DSL failure must cross the C boundary as an error, never a valid step."""

import ctypes
import shutil
from pathlib import Path

import pytest

from gicg_env import GicgEngine
from gicg_env.engine import ACTION_SKILL


@pytest.fixture
def broken_rules(tmp_path):
    data = Path(__file__).resolve().parents[2] / 'data'
    shutil.copytree(data / 'system', tmp_path / 'system')
    shutil.copytree(data / 'pools' / 'v_legacy', tmp_path / 'pools' / 'v_legacy')
    fault = tmp_path / 'pools' / 'v_legacy' / 'characters' / '赤蝶' / '赤蝶_故障.lua'
    fault.write_text(
        'on_skill_use(function(ctx)\n'
        '  if ctx.actor_player ~= 0 then return end\n'
        '  get_counter(ctx.skill_index, Scope.Global)\n'
        'end)\n',
        encoding='utf-8',
    )
    return tmp_path


@pytest.mark.parametrize('raw_call', [False, True])
def test_failed_rule_raises_and_requires_reset(broken_rules, raw_call):
    with GicgEngine() as eng:
        eng.new_game(players=[['赤蝶'], ['墨客']], seed=42, data_dir=str(broken_rules))
        eng.step(0)
        eng.step(0)
        eng.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 8])
        kinds, _ = eng.get_legal_actions()
        skill = next(i for i, kind in enumerate(kinds) if kind == ACTION_SKILL)
        if raw_call:
            raw = ctypes.CDLL(eng._lib._name)  # independent ctypes function objects, no errcheck
            raw.GameStep.argtypes = [ctypes.c_int, ctypes.c_int]
            raw.GameStep.restype = ctypes.c_int
            assert raw.GameStep(eng._handle, skill) == -1
            raw.GameClone.argtypes = [ctypes.c_int]
            raw.GameClone.restype = ctypes.c_int
            assert raw.GameClone(eng._handle) == -1, 'failed clone must not return a valid-looking handle 0'
        else:
            with pytest.raises(RuntimeError, match='unresolved_dependency'):
                eng.step(skill)
        for operation in (eng.get_dynamic_obs, eng.get_legal_actions, eng.snapshot):
            with pytest.raises(RuntimeError, match='DSL rule failed'):
                operation()
        eng.reset_dynamic(43)
        assert eng.get_legal_actions()[0].size > 0
