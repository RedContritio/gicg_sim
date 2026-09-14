"""Real DSL continuation survives native snapshots and Python clone handles."""

import shutil
from pathlib import Path

from gicg_env import GicgEngine
from gicg_env.engine import ACTION_SKILL, STEP_NEED_TARGET


def test_dsl_deferred_choice_survives_clone_and_restore(tmp_path):
    data = Path(__file__).resolve().parents[2] / 'data'
    shutil.copytree(data / 'system', tmp_path / 'system')
    shutil.copytree(data / 'pools' / 'v_legacy', tmp_path / 'pools' / 'v_legacy')
    rule = tmp_path / 'pools' / 'v_legacy' / 'characters' / '赤蝶' / '赤蝶_等待测试.lua'
    rule.write_text(
        'on_skill_use(function(ctx)\n'
        '  if ctx.actor_player ~= 0 then return end\n'
        '  request_switch(Player.Enemy)\n'
        '  defer_fn(function()\n'
        '    deal_damage(Target.EnemyActive, Element.Physical, 1)\n'
        '  end)\n'
        'end)\n',
        encoding='utf-8',
    )
    with GicgEngine() as eng:
        eng.new_game(players=[['赤蝶'], ['墨客', '刻师傅', '猫咪']], seed=42, data_dir=str(tmp_path))
        eng.step(0)
        eng.step(0)
        eng.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 8])
        kinds, _ = eng.get_legal_actions()
        skill = next(i for i, kind in enumerate(kinds) if kind == ACTION_SKILL)
        assert eng.step(skill) == STEP_NEED_TARGET
        assert eng.has_pending and eng.acting_player == 1 and eng.turn == 0
        waiting = eng.export_view()
        snapshot = eng.snapshot()
        try:
            for choice in (0, 1, 0):
                eng.restore(snapshot)
                eng.step_target(-1)
                assert eng.has_pending and eng.export_view() == waiting
                with eng.clone() as branch:
                    branch.step_target(choice)
                    assert not branch.has_pending and branch.turn == 1
                    after = branch.export_view()
                    assert after['players'][1]['active_char'] == choice + 1
                    for slot, char in enumerate(after['players'][1]['chars']):
                        expected = waiting['players'][1]['chars'][slot]['hp'] - int(slot == choice + 1)
                        assert char['hp'] == expected
                assert eng.has_pending and eng.export_view() == waiting
            eng.step_target(0)
            assert not eng.has_pending and eng.turn == 1
        finally:
            eng.snapshot_free(snapshot)
