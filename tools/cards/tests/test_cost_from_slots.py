"""tools.cards.cost_resolve.cost_from_slots 单元测试。

覆盖:mapping / 备源 hash / 全源一致 / 不一致 raise / override 命中 / character skill 模板。
"""

from __future__ import annotations

import pytest

from tools.cards.cost_resolve import cost_from_slots, skill_cost_template


class TestSkillCostTemplate:
    """skill_cost_template:基于 skill_type + element 推 expected cost / energy_req。"""

    def test_普通攻击(self):
        cost, eq = skill_cost_template('普通攻击', '火', raw_life=1, raw_energy=2)
        assert cost == {'火': 1, '无色': 2}
        assert eq == 0

    def test_元素战技(self):
        cost, eq = skill_cost_template('元素战技', '冰', raw_life=3, raw_energy=0)
        assert cost == {'冰': 3}
        assert eq == 0

    def test_元素爆发_读_raw_life(self):
        # 迪卢克爆发 raw_life=4 应得 {火:4} 不是 {火:3}
        cost, eq = skill_cost_template('元素爆发', '火', raw_life=4, raw_energy=3)
        assert cost == {'火': 4}
        assert eq == 3

    def test_被动技能(self):
        cost, eq = skill_cost_template('被动技能', '火', raw_life=0, raw_energy=0)
        assert cost == {}
        assert eq == 0

    def test_no_element(self):
        cost, eq = skill_cost_template('普通攻击', '', raw_life=1, raw_energy=2)
        assert cost is None  # 无 element 时返回 (None, 0) 跳过模板验证
        assert eq == 0

    def test_未知_skill_type(self):
        cost, eq = skill_cost_template('特殊技能', '火', raw_life=0, raw_energy=0)
        assert cost is None


class TestCostFromSlots:
    """cost_from_slots:全源严格交叉验证。"""

    def test_迪卢克普攻_mapping_only(self):
        # raw life=1, life_bg=4(火), energy=2, energy_bg=10(无色)
        cost, eq = cost_from_slots(1, 4, 2, 10)
        assert cost == {'火': 1, '无色': 2}
        assert eq == 0

    def test_迪卢克爆发_能量需求(self):
        # raw life=4, life_bg=4(火), energy=3, energy_bg=8(能量需求)
        cost, eq = cost_from_slots(4, 4, 3, 8)
        assert cost == {'火': 4}
        assert eq == 3

    def test_主源未知_bg_raise(self):
        with pytest.raises(ValueError, match='主源未知 bg=99'):
            cost_from_slots(3, 99, 0, 0)

    def test_空槽位_n_非零_raise(self):
        # life_bg=0(空)但 life=3 非 0 = 数据自洽性破坏
        with pytest.raises(ValueError, match='空槽位.*但 n=3 非 0'):
            cost_from_slots(3, 0, 0, 0)

    def test_skill_template_一致(self):
        # 标准普攻 raw life=1, life_bg=4(火), energy=2, energy_bg=10(无色) 与模板一致
        cost, eq = cost_from_slots(1, 4, 2, 10, skill_type='普通攻击', character_element='火')
        assert cost == {'火': 1, '无色': 2}

    def test_skill_template_不一致_raise(self):
        # 战技 cost=2(纳西妲式)与模板 expected {草:3} 不一致
        with pytest.raises(ValueError, match='skill 模板.*不一致'):
            cost_from_slots(2, 2, 0, 0, skill_type='元素战技', character_element='草')

    def test_attr_花费_total_一致(self):
        # 总数 cross-check
        cost, eq = cost_from_slots(1, 4, 2, 10, attr_花费_total=3)
        assert sum(cost.values()) == 3

    def test_attr_花费_total_不一致_raise(self):
        with pytest.raises(ValueError, match=r"attr\['花费'\]"):
            cost_from_slots(1, 4, 2, 10, attr_花费_total=99)

    def test_list_filter_花费_不一致_raise(self):
        with pytest.raises(ValueError, match='list filter 花费'):
            cost_from_slots(1, 4, 2, 10, list_filter_花费=99)
