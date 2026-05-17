"""tools.cards.extractors phrase / enum 严格化测试。"""

from __future__ import annotations

import pytest

from tools.cards.extractors import (
    extract_battle_action,
    extract_deck_constraint,
    extract_duration,
    extract_for_character,
    extract_generated_by,
    extract_weapon_type,
)


class TestExtractBattleAction:
    def test_html_strong_u_战斗行动(self):
        assert extract_battle_action('<strong><u>战斗行动</u></strong>:...') == '战斗行动'

    def test_html_strong_u_快速行动(self):
        assert extract_battle_action('<strong><u>快速行动</u></strong>') == '快速行动'

    def test_text_句首战斗行动(self):
        assert extract_battle_action('<p>战斗行动：装备此牌后...</p>') == '战斗行动'

    def test_text_句中不命中(self):
        # '战斗行动:' 不在句首/分隔符后
        assert extract_battle_action('某种战斗行动：不应被识别') == ''

    def test_no_action(self):
        assert extract_battle_action('<p>普通效果文本</p>') == ''


class TestExtractDuration:
    def test_可用次数(self):
        assert extract_duration('可用次数: 3') == '可用次数3'

    def test_持续回合(self):
        assert extract_duration('持续回合: 2') == '持续2回合'

    def test_句首本回合(self):
        assert extract_duration('本回合内造成伤害+1') == '持续本回合'

    def test_句中持续不命中(self):
        # 旧版 `'持续' in text` substring 误匹配,新版严格白名单不命中
        assert extract_duration('召唤物持续在场') == ''

    def test_no_duration(self):
        assert extract_duration('普通伤害效果') == ''


class TestExtractWeaponType:
    def test_裸_X角色(self):
        assert extract_weapon_type('双手剑角色装备此牌时...') == '双手剑'

    def test_括号_X_角色(self):
        assert extract_weapon_type('「弓」角色专用') == '弓'

    def test_no_weapon(self):
        assert extract_weapon_type('普通效果文本') == ''


class TestExtractGeneratedBy:
    def test_后缀_效果生成(self):
        assert extract_generated_by('砂糖效果生成') == '砂糖效果生成'

    def test_后缀_效果获得(self):
        assert extract_generated_by('卡牌效果获得') == '卡牌效果获得'

    def test_中间出现_raise(self):
        with pytest.raises(ValueError, match='不在末尾'):
            extract_generated_by('效果生成的卡')

    def test_空_string(self):
        assert extract_generated_by('') == ''

    def test_no_phrase(self):
        assert extract_generated_by('卡牌商店购买') == ''


class TestExtractForCharacter:
    def test_反向_enum_match(self):
        # 假设 character names enum 含 '砂糖'
        # 实际由 list_ext load_character_names 提供;此测试依赖 fetch_list 数据
        # 跳过若 list 数据缺
        try:
            result = extract_for_character('我方出战角色为砂糖时,装备此牌')
            assert result == '砂糖'
        except FileNotFoundError:
            pytest.skip('list 数据未 fetch')

    def test_no_character(self):
        try:
            assert extract_for_character('普通效果文本无角色限定') == ''
        except FileNotFoundError:
            pytest.skip('list 数据未 fetch')


class TestExtractDeckConstraint:
    def test_才能加入牌组(self):
        assert extract_deck_constraint('（牌组中包含迪卢克，才能加入牌组）') == '牌组中包含迪卢克，才能加入牌组'

    def test_至少_角色_with_才能加入(self):
        assert (
            extract_deck_constraint('（牌组中至少含3个火元素角色，才能加入牌组）')
            == '牌组中至少含3个火元素角色，才能加入牌组'
        )

    def test_misleading_至少_角色_no_才能加入_rejected(self):
        # 旧版 '至少' + '角色' substring AND 会误匹配此句;新版严格 require '才能加入牌组'
        assert extract_deck_constraint('（至少打出X牌时为该角色生成效果）') == ''

    def test_no_constraint(self):
        assert extract_deck_constraint('普通卡牌效果') == ''
