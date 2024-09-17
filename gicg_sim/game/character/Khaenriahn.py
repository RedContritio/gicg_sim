from typing import MutableSequence

from ...constants.element import DamageElement, Element
from ...constants.id import CharacterID
from ...constants.target import TargetDescType, TargetType
from ..event._base import BaseEvent
from ._base import Character


class Khaenriahn(Character):
    '''
    坎瑞亚人（测试用角色）
    '''

    def __init__(self, id: CharacterID) -> None:
        super().__init__("Khaenriahn", 10, 2, Element.Pyro, id=id)

    def _make_simple_physical_damage(self, value: int):
        return self._make_damage(TargetType(TargetDescType.active), DamageElement.Physical, value)

    def normal_attack(self, events: MutableSequence[BaseEvent]):
        events.append(self._make_simple_physical_damage(2))

    def elemental_skill(self, events: MutableSequence[BaseEvent]):
        events.append(self._make_simple_physical_damage(3))

    def elemental_burst(self, events: MutableSequence[BaseEvent]):
        events.append(self._make_simple_physical_damage(6))

    def use_skill(self, events: MutableSequence[BaseEvent], skill):
        if skill == "normal_attack":
            self.normal_attack(events)
        elif skill == "elemental_skill":
            self.elemental_skill(events)
        elif skill == "elemental_burst":
            self.elemental_burst(events)
        else:
            raise ValueError(f"Unknown skill: {skill}")
