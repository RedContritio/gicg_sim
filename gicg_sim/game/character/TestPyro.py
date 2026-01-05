from typing import MutableSequence

from gicg_sim.game.state import State

from ...constants.element import CostElement, DamageElement, Element
from ...constants.id import CharacterID
from ..event._base import BaseEvent
from ..skill import Skill_NormalAttack, make_normal_attack_cost
from ._base import Character


class TestPyro(Character):
    '''
    测试用火元素角色
    - 10 HP, 2 能量上限
    - 普通攻击: 2 物理伤害, 消耗 1火 + 2任意
    '''

    def __init__(self, id: CharacterID) -> None:
        super().__init__("TestPyro", 10, 2, Element.Pyro, id=id)
        normal_attack = Skill_NormalAttack(
            "普通攻击",
            DamageElement.Physical,
            make_normal_attack_cost(
                CostElement.Pyro,
                1,
                2),
            damage_count=2)

        self._set_skills([
            normal_attack,
        ])

    def use_skill(self, state: State,
                  events: MutableSequence[BaseEvent], skill: str):
        if skill == "normal_attack":
            if self.normal_attack is None:
                raise ValueError("normal_attack skill not found")
            self.normal_attack.apply(state, events)
        else:
            raise ValueError(f"Unknown skill: {skill}")

