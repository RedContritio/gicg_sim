"""The audit uses resolved scenarios, including inherited decks and card pools."""

from tools.cards.effect_audit import game_config


def test_current_training_config_preserves_explicit_decks_and_pools():
    cfg = game_config('configs/dmc/stage3_b_v_legacy.toml')
    assert cfg['players'][0]['chars'] == [{'name': '赤蝶'}]
    assert cfg['players'][1]['chars'] == [{'name': '墨客'}]
    assert len(cfg['players'][0]['deck']) == 15
    assert '蝶鳞' in cfg['players'][0]['deck']
    assert '守正' in cfg['players'][1]['deck']
    assert '以逸待劳' in cfg['card_pool']
    assert cfg['pools'] == ['v_legacy']


def test_audit_resolves_inherited_scenario(tmp_path):
    (tmp_path / 'base.toml').write_text('[scenario]\nteam_0=["赤蝶"]\nteam_1=["墨客"]\ncard_pool=["荷花酥"]\n')
    child = tmp_path / 'child.toml'
    child.write_text('[meta]\nextends="base.toml"\n[scenario]\nmax_rounds=4\n')
    cfg = game_config(child)
    assert cfg['card_pool'] == ['荷花酥']
    assert cfg['max_rounds'] == 4
