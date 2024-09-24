from typing import MutableSequence

from gicg_sim.game.state import State

from ...constants.element import DamageElement, Element
from ...constants.id import CharacterID
from ..event._base import BaseEvent
from ..skill import Skill_NormalAttack, make_normal_attack_cost
from ._base import Character


class Khaenriahn(Character):
    '''
    坎瑞亚人（测试用角色）
    '''

    def __init__(self, id: CharacterID) -> None:
        super().__init__("Khaenriahn", 10, 2, Element.Undefined, id=id)
        self.normal_attack = Skill_NormalAttack(
            "普通攻击",
            DamageElement.Physical,
            make_normal_attack_cost(
                None,
                0,
                3),
            2)

        self._set_skills([
            self.normal_attack,
        ])

    def use_skill(self, state: State,
                  events: MutableSequence[BaseEvent], skill):
        if skill == "normal_attack":
            self.normal_attack.apply(state, events)
        else:
            raise ValueError(f"Unknown skill: {skill}")
